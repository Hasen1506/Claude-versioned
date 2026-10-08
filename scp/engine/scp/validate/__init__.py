"""Readiness gate — master-data checks before any plan runs (S/4 guide §3 "master data readiness
gate": most "the system planned it wrong" incidents are master-data defects).

Every rule has a stable code, a severity, the offending object, and a fix hint. Errors block
planning; warnings are shown with the plan. Rules are listed in :data:`RULES` so the UI and the
docs can enumerate them, and each one has a positive and negative test.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ..model import (
    Dataset, DemandKind, LocationType, SafetyStockMethod, Strategy, TransportMode,
)
from ..model.common import PRODUCTION_LOCATION_TYPES, STOCKING_LOCATION_TYPES
from ..network import build_graph

Severity = Literal["error", "warning"]


class Issue(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    code: str
    severity: Severity
    object_type: str
    object_id: str
    message: str
    hint: str = ""
    field: str | None = None


RULES: dict[str, tuple[Severity, str]] = {
    "DUP_ID": ("error", "Duplicate id within an object type"),
    "DUP_LOCATION_PRODUCT": ("error", "Location-product maintained twice"),
    "REF_UNKNOWN": ("error", "Reference to an object that does not exist"),
    "REF_WRONG_TYPE": ("error", "Reference to a location of the wrong type"),
    "FX_MISSING": ("error", "Foreign currency without an exchange rate"),
    "CALENDAR_NO_WORKDAY_IN_HORIZON": ("error", "Calendar has no working day in the horizon"),
    "BOM_CYCLE": ("error", "Circular sourcing (BOM or transfer loop)"),
    "NO_SOURCE": ("error", "A node with requirements has no way to be replenished"),
    "LANE_WEIGHT_MISSING": ("error", "Lane costed per kg/m³ but product weight/volume missing"),
    "RESOURCE_WRONG_LOCATION": ("error", "Operation uses a resource at another location"),
    "SS_NO_VARIABILITY": ("error", "Statistical safety stock without demand variability"),
    "SOURCE_NOT_VALID_IN_HORIZON": ("warning", "Source validity does not cover the horizon"),
    "PRODUCTION_NO_OPERATIONS": ("warning", "Production source without operations: no capacity load"),
    "PRODUCTION_NO_LEAD_TIME": ("warning", "Production source with neither routing nor fixed lead time"),
    "PURCHASE_ZERO_LEAD_TIME": ("warning", "Purchasing source with zero lead time"),
    "SS_AND_SAFETY_TIME": ("warning", "Safety stock and safety time both set: double buffering"),
    "QUOTA_SUM": ("warning", "Quotas for a node do not add up to 1"),
    "DEMAND_OUTSIDE_HORIZON": ("warning", "Demand outside the planning horizon is ignored"),
    "DEMAND_PAST_DUE": ("warning", "Demand before planning start is treated as backlog"),
    "MTO_WITH_FORECAST": ("warning", "Forecast on an MTO product is ignored"),
    "CONSUMPTION_GAP": ("warning", "Sales orders on some days can reach no forecast to consume: forecast and orders "
                                   "are both planned"),
    "FORECAST_TWICE": ("warning", "Forecast at a place and at a customer it supplies: both are planned"),
    "FORECAST_INPUTS_CHANGED": ("warning", "Demand events, overrides or forecast settings changed after the forecast "
                                           "was last used in the plan"),
    "STOCK_AT_CUSTOMER": ("warning", "Stock maintained at a customer location is not planned"),
    "RESOURCE_UNUSED": ("warning", "Resource not used by any operation"),
    "LOCATION_PRODUCT_DEFAULTED": ("warning", "Planning node without a location-product: defaults used"),
    "SHELF_LIFE_VS_LEAD_TIME": ("warning", "Replenishment lead time exceeds shelf life"),
    "HISTORY_AFTER_START": ("warning", "Sales history on or after planning start is not used"),
    "NPI_LIKE_WITHOUT_HISTORY": ("warning", "NPI like product has no sales history at that location"),
    "NPI_DUPLICATE": ("warning", "More than one NPI rule for the same location-product"),
    "OVERRIDE_OUTSIDE_HORIZON": ("warning", "Consensus override outside the forecast horizon is ignored"),
    "OVERRIDE_WITHOUT_FORECAST": ("warning", "Consensus override for a series with no history or NPI rule"),
    "CONFIRMATION_ORPHAN": ("warning", "Persisted confirmation for an order that no longer exists"),
    "STOCK_NOT_SYNCED": ("warning", "On-hand differs from the goods-movement journal"),
    "NEGATIVE_STOCK": ("warning", "The movement journal takes stock below zero"),
    "STOCK_EXPIRED": ("warning", "Stock in batches past their expiry date"),
    "BATCH_UNKNOWN": ("warning", "Goods movement in a batch with no batch record"),
    "REVERSAL_UNKNOWN": ("warning", "Reversal of a movement that is not in the journal"),
    "SERIALS_COUNT": ("warning", "Serial numbers that do not match the quantity"),
    "COLD_CHAIN_LANE": ("warning", "Chilled product on a route without refrigeration"),
    "MOVEMENT_REF_UNKNOWN": ("warning", "Goods movement references no open or closed order"),
    "PHANTOM_NOT_MADE": ("warning", "Phantom assembly that is not made at that plant"),
    "PO_LINE_MISMATCH": ("error", "Purchase order line that does not match its order"),
    "FIXED_SOURCE_TWICE": ("warning", "More than one fixed source for a product at a place"),
    "OPEN_PO_BLOCKED_SUPPLIER": ("warning", "Open purchase order with a blocked supplier"),
}


class _Collector:
    def __init__(self) -> None:
        self.issues: list[Issue] = []

    def add(self, code: str, object_type: str, object_id: str, message: str, hint: str = "",
            field: str | None = None) -> None:
        sev, _ = RULES[code]
        self.issues.append(Issue(code=code, severity=sev, object_type=object_type,
                                 object_id=object_id, message=message, hint=hint, field=field))


def validate(ds: Dataset) -> list[Issue]:
    c = _Collector()
    _duplicates(ds, c)
    _references(ds, c)
    _currency(ds, c)
    _calendars(ds, c)
    _production(ds, c)
    _purchasing(ds, c)
    _lanes(ds, c)
    _policies(ds, c)
    _demand(ds, c)
    _forecasting(ds, c)
    _graph(ds, c)
    _movements(ds, c)
    order = {"error": 0, "warning": 1}
    c.issues.sort(key=lambda i: (order[i.severity], i.code, i.object_type, i.object_id))
    return c.issues


def has_errors(issues: list[Issue]) -> bool:
    return any(i.severity == "error" for i in issues)


_DEMAND_CODES = {"DUP_ID", "DUP_LOCATION_PRODUCT", "REF_UNKNOWN", "REF_WRONG_TYPE"}
_DEMAND_OBJECTS = {"history", "event", "npi", "override", "demand", "location", "product"}


def blocks_demand(issues: list[Issue]) -> bool:
    """Errors that stop demand planning: broken identities or references in its own inputs. Supply-side
    defects (no source, BOM cycles, lanes, capacity, safety-stock parameters) block supply planning only, so a
    demand planner can forecast while the supply network is still being set up."""
    return any(i.severity == "error" and i.code in _DEMAND_CODES and i.object_type in _DEMAND_OBJECTS for i in issues)


# ---------------------------------------------------------------------------------------------
def _duplicates(ds: Dataset, c: _Collector) -> None:
    groups = {
        "calendar": ds.calendars, "location": ds.locations, "product": ds.products,
        "resource": ds.resources, "production_source": ds.production_sources,
        "purchasing_source": ds.purchasing_sources, "lane": ds.lanes, "receipt": ds.receipts,
        "movement": ds.movements, "capacity_option": ds.finance.capacity_options,
        "purchase_order": ds.purchase_orders, "inventory_doc": ds.inventory_docs, "mrp_group": ds.mrp_groups,
    }
    for typ, items in groups.items():
        for oid, n in Counter(i.id for i in items).items():
            if n > 1:
                c.add("DUP_ID", typ, oid, f"{typ} id '{oid}' is used {n} times", "Ids must be unique per type")
    for (prod, bid), n in Counter((b.product, b.id) for b in ds.batches).items():
        if n > 1:
            c.add("DUP_ID", "batch", f"{prod}/{bid}", f"batch {bid} of {prod} is kept {n} times",
                  "A batch number is unique per product")
    for sup, n in Counter(v.supplier for v in ds.vendors).items():
        if n > 1:
            c.add("DUP_ID", "vendor", sup, f"supplier '{sup}' has {n} purchasing records; the first is used",
                  "Keep one record per supplier")
    for oid, n in Counter(d.id for d in ds.demand if d.kind is DemandKind.SALES_ORDER and d.id).items():
        if n > 1:
            c.add("DUP_ID", "demand", oid, f"sales order '{oid}' is used {n} times",
                  "Give each sales order its own number")
    for (cu, prod), n in Counter((cp.customer, cp.product) for cp in ds.customer_prices).items():
        if n > 1:
            c.add("DUP_ID", "customer_price", f"{cu}/{prod}", f"{prod} has {n} prices for {cu}; the first is used",
                  "Keep one price per customer and product")
    for (loc, prod), n in Counter((lp.location, lp.product) for lp in ds.location_products).items():
        if n > 1:
            c.add("DUP_LOCATION_PRODUCT", "location_product", f"{loc}/{prod}",
                  f"{prod} at {loc} is maintained {n} times; the first record is used",
                  "Keep exactly one planning record")


def _ref(ds: Dataset, c: _Collector, kind: str, value: str | None, typ: str, oid: str, field: str) -> bool:
    if value is None:
        return True
    index = {"location": ds.location_by_id, "product": ds.product_by_id,
             "calendar": ds.calendar_by_id, "resource": ds.resource_by_id,
             "mrp_group": {g.id: g for g in ds.mrp_groups},
             "payment_terms": ds.payment_terms_by_id}[kind]
    if value not in index:
        c.add("REF_UNKNOWN", typ, oid, f"{field} refers to unknown {kind} '{value}'",
              f"Create {kind} '{value}' or fix the reference", field)
        return False
    return True


def _loc_type(ds: Dataset, c: _Collector, loc: str, allowed: set[LocationType], typ: str, oid: str,
              field: str, what: str) -> None:
    t = ds.location_type(loc)
    if t is not None and t not in allowed:
        c.add("REF_WRONG_TYPE", typ, oid, f"{field} '{loc}' is a {t.value}; {what}",
              "Pick a location of the right type", field)


def _references(ds: Dataset, c: _Collector) -> None:
    s = ds.settings
    _ref(ds, c, "calendar", s.default_calendar, "settings", "settings", "default_calendar")
    for loc in ds.locations:
        _ref(ds, c, "calendar", loc.calendar, "location", loc.id, "calendar")
    for lp in ds.location_products:
        oid = f"{lp.location}/{lp.product}"
        _ref(ds, c, "location", lp.location, "location_product", oid, "location")
        _ref(ds, c, "product", lp.product, "location_product", oid, "product")
        if ds.location_type(lp.location) is LocationType.CUSTOMER and lp.on_hand > 0:
            c.add("STOCK_AT_CUSTOMER", "location_product", oid, "Customer locations do not hold planned stock",
                  "Model consignment stock at a DC instead")
        _loc_type(ds, c, lp.location, STOCKING_LOCATION_TYPES | {LocationType.CUSTOMER},
                  "location_product", oid, "location", "suppliers are not planned")
        _ref(ds, c, "mrp_group", lp.mrp_group, "location_product", oid, "mrp_group")
        _ref(ds, c, "product", lp.follow_up, "location_product", oid, "follow_up")
        if _ref(ds, c, "location", lp.withdraw_from, "location_product", oid, "withdraw_from"):
            if lp.withdraw_from:
                _loc_type(ds, c, lp.withdraw_from, STOCKING_LOCATION_TYPES, "location_product", oid, "withdraw_from",
                          "parts are withdrawn from a place that keeps stock")
    for r in ds.resources:
        if _ref(ds, c, "location", r.location, "resource", r.id, "location"):
            _loc_type(ds, c, r.location, PRODUCTION_LOCATION_TYPES, "resource", r.id, "location",
                      "resources belong to plants")
        _ref(ds, c, "calendar", r.calendar, "resource", r.id, "calendar")
    for ps in ds.production_sources:
        if _ref(ds, c, "location", ps.location, "production_source", ps.id, "location"):
            _loc_type(ds, c, ps.location, PRODUCTION_LOCATION_TYPES, "production_source", ps.id,
                      "location", "production happens at plants")
        _ref(ds, c, "product", ps.product, "production_source", ps.id, "product")
        for comp in ps.components:
            _ref(ds, c, "product", comp.product, "production_source", ps.id, "components.product")
        for alt in ps.bom_alternatives:
            for comp in alt.components:
                _ref(ds, c, "product", comp.product, "production_source", ps.id,
                     f"bom_alternatives[{alt.id}].components.product")
        for co in ps.co_products:
            _ref(ds, c, "product", co.product, "production_source", ps.id, "co_products.product")
        for op in ps.operations:
            _ref(ds, c, "resource", op.resource, "production_source", ps.id, f"operations[{op.seq}].resource")
            _ref(ds, c, "resource", op.labor_resource, "production_source", ps.id,
                 f"operations[{op.seq}].labor_resource")
            for alt in op.alternatives:
                _ref(ds, c, "resource", alt, "production_source", ps.id, f"operations[{op.seq}].alternatives")
            for t in op.tools:
                _ref(ds, c, "resource", t, "production_source", ps.id, f"operations[{op.seq}].tools")
            if op.subcontract is not None and _ref(ds, c, "location", op.subcontract.supplier, "production_source",
                                                   ps.id, f"operations[{op.seq}].subcontract.supplier"):
                _loc_type(ds, c, op.subcontract.supplier, {LocationType.SUPPLIER}, "production_source", ps.id,
                          f"operations[{op.seq}].subcontract.supplier", "work done outside needs a supplier")
    for pu in ds.purchasing_sources:
        if _ref(ds, c, "location", pu.supplier, "purchasing_source", pu.id, "supplier"):
            _loc_type(ds, c, pu.supplier, {LocationType.SUPPLIER}, "purchasing_source", pu.id, "supplier",
                      "a purchasing source must name a supplier location")
        if _ref(ds, c, "location", pu.location, "purchasing_source", pu.id, "location"):
            _loc_type(ds, c, pu.location, STOCKING_LOCATION_TYPES, "purchasing_source", pu.id, "location",
                      "goods must be received at a stocking location")
        _ref(ds, c, "product", pu.product, "purchasing_source", pu.id, "product")
    for ln in ds.lanes:
        _ref(ds, c, "location", ln.origin, "lane", ln.id, "origin")
        _ref(ds, c, "location", ln.destination, "lane", ln.id, "destination")
        _loc_type(ds, c, ln.origin, STOCKING_LOCATION_TYPES | {LocationType.SUPPLIER}, "lane", ln.id,
                  "origin", "lanes cannot start at a customer")
        _loc_type(ds, c, ln.destination, STOCKING_LOCATION_TYPES | {LocationType.CUSTOMER}, "lane", ln.id,
                  "destination", "lanes cannot end at a supplier")
        for p in ln.products or []:
            _ref(ds, c, "product", p, "lane", ln.id, "products")
    for i, d in enumerate(ds.demand):
        oid = d.id or f"#{i}"
        if _ref(ds, c, "location", d.location, "demand", oid, "location"):
            _loc_type(ds, c, d.location, STOCKING_LOCATION_TYPES | {LocationType.CUSTOMER}, "demand", oid,
                      "location", "demand cannot occur at a supplier")
        _ref(ds, c, "product", d.product, "demand", oid, "product")
    for cp in ds.customer_prices:
        oid = f"{cp.customer}/{cp.product}"
        if _ref(ds, c, "location", cp.customer, "customer_price", oid, "customer"):
            _loc_type(ds, c, cp.customer, STOCKING_LOCATION_TYPES | {LocationType.CUSTOMER}, "customer_price", oid,
                      "customer", "a selling price belongs to a customer (or a place that sells)")
        _ref(ds, c, "product", cp.product, "customer_price", oid, "product")
    for i, hr in enumerate(ds.history):
        oid = f"#{i}"
        if _ref(ds, c, "location", hr.location, "history", oid, "location"):
            _loc_type(ds, c, hr.location, STOCKING_LOCATION_TYPES | {LocationType.CUSTOMER}, "history", oid,
                      "location", "sales history belongs to a customer or stocking location")
        _ref(ds, c, "product", hr.product, "history", oid, "product")
    for e in ds.events:
        for p in e.products:
            _ref(ds, c, "product", p, "event", e.id, "products")
        for loc in e.locations:
            _ref(ds, c, "location", loc, "event", e.id, "locations")
    for n in ds.npi:
        oid = f"{n.location}/{n.product}"
        for fld, kind in (("location", "location"), ("product", "product"), ("like_product", "product"),
                          ("like_location", "location")):
            _ref(ds, c, kind, getattr(n, fld), "npi", oid, fld)
    for o in ds.overrides:
        oid = f"{o.location}/{o.product}@{o.date.isoformat()}"
        _ref(ds, c, "location", o.location, "override", oid, "location")
        _ref(ds, c, "product", o.product, "override", oid, "product")
    so_ids = {d.id for d in ds.demand if d.kind is DemandKind.SALES_ORDER and d.id}
    for a in ds.allocations:
        _ref(ds, c, "product", a.product, "allocation", a.id, "product")
        for cu in a.customers:
            _ref(ds, c, "location", cu, "allocation", a.id, "customers")
    for i, cf in enumerate(ds.confirmations):
        _ref(ds, c, "location", cf.ship_from, "confirmation", f"#{i}", "ship_from")
        if cf.order not in so_ids:
            c.add("CONFIRMATION_ORPHAN", "confirmation", f"#{i}", f"Confirmation for {cf.order}, which is not an open sales order",
                  "Remove it, or re-run promising and commit")
    for sg in ds.promising.bop_segments:
        for cu in sg.customers:
            _ref(ds, c, "location", cu, "bop_segment", sg.name, "customers")
        for p in sg.products:
            _ref(ds, c, "product", p, "bop_segment", sg.name, "products")
    for i, co in enumerate(ds.changeovers):
        _ref(ds, c, "resource", co.resource, "changeover", f"#{i}", "resource")
    for r in ds.receipts:
        if _ref(ds, c, "location", r.location, "receipt", r.id, "location"):
            _loc_type(ds, c, r.location, STOCKING_LOCATION_TYPES, "receipt", r.id, "location",
                      "receipts land at stocking locations")
        _ref(ds, c, "product", r.product, "receipt", r.id, "product")
        for rv in r.reservations:
            _ref(ds, c, "location", rv.location, "receipt", r.id, "reservations.location")
            _ref(ds, c, "product", rv.product, "receipt", r.id, "reservations.product")
    for v in ds.vendors:
        if _ref(ds, c, "location", v.supplier, "vendor", v.supplier, "supplier"):
            _loc_type(ds, c, v.supplier, {LocationType.SUPPLIER}, "vendor", v.supplier, "supplier",
                      "purchasing data belongs to a supplier location")
    for po in ds.purchase_orders:
        if _ref(ds, c, "location", po.supplier, "purchase_order", po.id, "supplier"):
            _loc_type(ds, c, po.supplier, {LocationType.SUPPLIER}, "purchase_order", po.id, "supplier",
                      "a purchase order goes to a supplier")
        if _ref(ds, c, "location", po.location, "purchase_order", po.id, "location"):
            _loc_type(ds, c, po.location, STOCKING_LOCATION_TYPES, "purchase_order", po.id, "location",
                      "goods must be received at a stocking location")
    for m in ds.movements:
        if _ref(ds, c, "location", m.location, "movement", m.id, "location"):
            _loc_type(ds, c, m.location, STOCKING_LOCATION_TYPES, "movement", m.id, "location",
                      "stock moves at stocking locations")
        _ref(ds, c, "product", m.product, "movement", m.id, "product")
        _ref(ds, c, "location", m.counterparty, "movement", m.id, "counterparty")
    for b in ds.batches:
        _ref(ds, c, "product", b.product, "batch", f"{b.product}/{b.id}", "product")
    for d in ds.inventory_docs:
        for it in d.items:
            _ref(ds, c, "location", it.location, "inventory_doc", d.id, "items")
            _ref(ds, c, "product", it.product, "inventory_doc", d.id, "items")
    for co in ds.finance.capacity_options:
        _ref(ds, c, "resource", co.resource, "capacity_option", co.id, "resource")
    for i, rule in enumerate(ds.tower.owners):
        for loc in rule.locations:
            _ref(ds, c, "location", loc, "owner_rule", f"#{i + 1} {rule.owner}", "locations")
        for prod in rule.products:
            _ref(ds, c, "product", prod, "owner_rule", f"#{i + 1} {rule.owner}", "products")
    for rid in ds.sop.capacity_add_hours_per_week:
        _ref(ds, c, "resource", rid, "sop", "sop", "capacity_add_hours_per_week")


def _currency(ds: Dataset, c: _Collector) -> None:
    s = ds.settings
    for pu in ds.purchasing_sources:
        cur = ds.price_currency(pu)
        if cur and cur != s.currency and cur not in s.fx_rates:
            c.add("FX_MISSING", "purchasing_source", pu.id, f"No exchange rate for {cur}",
                  f"Enter what one {cur} costs in {s.currency} (company settings → exchange rates)", "currency")


def _calendars(ds: Dataset, c: _Collector) -> None:
    from ..time import WorkCalendar

    s = ds.settings
    for cal in ds.calendars:
        wc = WorkCalendar(cal)
        if wc.workdays_between(s.planning_start, s.planning_start + timedelta(days=s.horizon_days)) == 0:
            c.add("CALENDAR_NO_WORKDAY_IN_HORIZON", "calendar", cal.id,
                  "No working day inside the plan's dates", "Check its working weekdays and holidays")


def _covers(valid_from, valid_to, start, end) -> bool:
    return (valid_from is None or valid_from <= start) and (valid_to is None or valid_to >= end)


def _production(ds: Dataset, c: _Collector) -> None:
    s = ds.settings
    end = s.planning_start + timedelta(days=s.horizon_days - 1)
    used: set[str] = set()
    for ps in ds.production_sources:
        if not ps.operations:
            c.add("PRODUCTION_NO_OPERATIONS", "production_source", ps.id,
                  f"{ps.product} at {ps.location} has no routing; it will not load any resource",
                  "Add operations with resource, setup and run hours")
            if ps.fixed_lead_time_workdays is None:
                c.add("PRODUCTION_NO_LEAD_TIME", "production_source", ps.id,
                      "Production lead time will be 0 days", "Add operations or fixed_lead_time_workdays")
        for op in ps.operations:
            used.update(x for x in (op.resource, op.labor_resource, *op.alternatives, *op.tools) if x)
            for rid in (op.resource, op.labor_resource, *op.alternatives, *op.tools):
                r = ds.resource_by_id.get(rid) if rid else None
                if r is not None and r.location != ps.location:
                    c.add("RESOURCE_WRONG_LOCATION", "production_source", ps.id,
                          f"Operation {op.seq} uses {rid} located at {r.location}, not {ps.location}",
                          "Use a resource of the producing plant", f"operations[{op.seq}]")
        if not _covers(ps.valid_from, ps.valid_to, s.planning_start, end):
            c.add("SOURCE_NOT_VALID_IN_HORIZON", "production_source", ps.id,
                  "Its valid-from and valid-to dates don't cover the whole plan; outside them it is not used",
                  "Extend valid_from/valid_to or add another source")
    made = {(ps.location, ps.product) for ps in ds.production_sources}
    for lp in ds.location_products:
        if lp.phantom and (lp.location, lp.product) not in made:
            c.add("PHANTOM_NOT_MADE", "location_product", f"{lp.location}/{lp.product}",
                  "Marked as a phantom assembly, but it is not made here, so its parts can't be passed through; "
                  "it is planned as an ordinary part",
                  "Add how it is made here, or clear the phantom mark", "phantom")
    for r in ds.resources:
        if r.id not in used:
            c.add("RESOURCE_UNUSED", "resource", r.id, "No operation uses this resource",
                  "Reference it in a routing or remove it")


def _purchasing(ds: Dataset, c: _Collector) -> None:
    s = ds.settings
    end = s.planning_start + timedelta(days=s.horizon_days - 1)
    for pu in ds.purchasing_sources:
        if pu.lead_time_days == 0:
            has_lane = any(ln.origin == pu.supplier and ln.destination == pu.location and ln.carries(pu.product)
                           and ln.planning_mode.transit_days > 0 for ln in ds.lanes)
            if not has_lane:
                c.add("PURCHASE_ZERO_LEAD_TIME", "purchasing_source", pu.id,
                      "Supplier lead time is 0 and there is no transit lane", "Enter the planned delivery time")
        if not _covers(pu.valid_from, pu.valid_to, s.planning_start, end):
            c.add("SOURCE_NOT_VALID_IN_HORIZON", "purchasing_source", pu.id,
                  "Its valid-from and valid-to dates don't cover the whole plan", "Extend the dates or add another source")


    fixed: dict[tuple[str, str], list] = {}
    for pu in ds.purchasing_sources:
        if pu.fixed and not ds.source_blocked(pu):
            fixed.setdefault((pu.location, pu.product), []).append(pu)
    for (loc, prod), pus in fixed.items():
        for i, a in enumerate(pus):
            for b in pus[i + 1:]:
                if _overlap(a, b):
                    c.add("FIXED_SOURCE_TWICE", "purchasing_source", b.id,
                          f"{prod} at {loc} has two fixed sources at the same time ({a.id} and {b.id}); "
                          f"planning uses {min(a, b, key=lambda x: (x.priority, x.id)).id}",
                          "Keep one fixed source per period, or give them dates that do not overlap", "fixed")
    _purchase_orders(ds, c)
    _sales(ds, c)
    _procure(ds, c)


def _overlap(a, b) -> bool:
    lo = max(a.valid_from or date.min, b.valid_from or date.min)
    hi = min(a.valid_to or date.max, b.valid_to or date.max)
    return lo <= hi


def _purchase_orders(ds: Dataset, c: _Collector) -> None:
    open_on: dict[str, int] = Counter()
    for r in ds.receipts:
        if r.po is None:
            continue
        po = ds.purchase_order_by_id.get(r.po)
        if po is None:
            c.add("REF_UNKNOWN", "receipt", r.id, f"po refers to unknown purchase order '{r.po}'",
                  f"Create purchase order '{r.po}' or clear the reference", "po")
            continue
        src = ds.purchasing_source_by_id.get(r.source or "")
        why = ("it is not a purchase" if r.kind.value != "purchase"
               else f"it is received at {r.location}, the order at {po.location}" if r.location != po.location
               else f"its source {src.id} is bought from {src.supplier}, the order goes to {po.supplier}"
               if src is not None and src.supplier != po.supplier else None)
        if why:
            c.add("PO_LINE_MISMATCH", "receipt", r.id, f"Line {r.id} is on purchase order {po.id} but {why}",
                  "Move the line to a matching order, or fix it", "po")
        open_on[po.supplier] += 1
    for pu_sup, n in open_on.items():
        v = ds.vendor_by_supplier.get(pu_sup)
        if v is not None and v.blocked:
            c.add("OPEN_PO_BLOCKED_SUPPLIER", "vendor", pu_sup,
                  f"{n} open purchase order line{'s' if n != 1 else ''} with {pu_sup}, which is blocked for purchasing"
                  + (f" ({v.block_reason})" if v.block_reason else ""),
                  "Receive or cancel them, or lift the block; planning still counts them")


def _sales(ds: Dataset, c: _Collector) -> None:
    """Customers' sales data, payment terms and the order-to-cash documents name what exists."""
    sell = STOCKING_LOCATION_TYPES | {LocationType.CUSTOMER}
    _ref(ds, c, "payment_terms", ds.sales.payment_terms, "settings", "sales", "payment_terms")
    for cu in ds.customers:
        if _ref(ds, c, "location", cu.customer, "customer", cu.customer, "customer"):
            _loc_type(ds, c, cu.customer, sell, "customer", cu.customer, "customer", "a supplier is not a customer")
        _ref(ds, c, "payment_terms", cu.payment_terms, "customer", cu.customer, "payment_terms")
    for typ, docs in (("sales_order", ds.sales_orders), ("quotation", ds.quotations), ("delivery", ds.deliveries),
                      ("invoice", ds.invoices), ("return", ds.returns)):
        for x in docs:
            _ref(ds, c, "location", x.customer, typ, x.id, "customer")
            if getattr(x, "payment_terms", None):
                _ref(ds, c, "payment_terms", x.payment_terms, typ, x.id, "payment_terms")
    for q in ds.quotations:
        for ln in q.lines:
            _ref(ds, c, "product", ln.product, "quotation", q.id, "lines.product")
    for dl in ds.deliveries:
        _ref(ds, c, "location", dl.ship_from, "delivery", dl.id, "ship_from")
    for r in ds.returns:
        _ref(ds, c, "product", r.product, "return", r.id, "product")
        _ref(ds, c, "location", r.location, "return", r.id, "location")
    headers = {o.id: o for o in ds.sales_orders}
    for i, d in enumerate(ds.demand):
        if d.order is None or d.kind is not DemandKind.SALES_ORDER:
            continue
        h = headers.get(d.order)
        oid = d.id or f"#{i}"
        if h is None:
            c.add("REF_UNKNOWN", "demand", oid, f"order refers to unknown sales order '{d.order}'",
                  f"Create sales order '{d.order}' or clear the reference", "order")
        elif h.customer != d.location:
            c.add("SO_LINE_MISMATCH", "demand", oid, f"Line {oid} is on sales order {h.id} for {h.customer} but is "
                  f"for {d.location}", "Move the line to an order for its customer, or fix it", "order")


def _procure(ds: Dataset, c: _Collector) -> None:
    """Suppliers' payment terms, contracts, scheduling agreements, supplier invoices and returns name what exists."""
    sup = {LocationType.SUPPLIER}
    for v in ds.vendors:
        _ref(ds, c, "payment_terms", v.payment_terms, "vendor", v.supplier, "payment_terms")
    for k in ds.contracts:
        if _ref(ds, c, "location", k.supplier, "contract", k.id, "supplier"):
            _loc_type(ds, c, k.supplier, sup, "contract", k.id, "supplier", "a contract is with a supplier")
        _ref(ds, c, "location", k.location, "contract", k.id, "location")
        for ln in k.lines:
            _ref(ds, c, "product", ln.product, "contract", k.id, "lines.product")
    for po in ds.purchase_orders:
        if po.kind == "scheduling_agreement":
            if po.product is None:
                c.add("SA_NO_PRODUCT", "purchase_order", po.id, f"Scheduling agreement {po.id} has no product",
                      "Give the product it schedules", "product")
            else:
                _ref(ds, c, "product", po.product, "purchase_order", po.id, "product")
    for inv in ds.supplier_invoices:
        _ref(ds, c, "location", inv.supplier, "supplier_invoice", inv.id, "supplier")
        for ln in inv.lines:
            _ref(ds, c, "product", ln.product, "supplier_invoice", inv.id, "lines.product")
    for r in ds.supplier_returns:
        _ref(ds, c, "location", r.supplier, "supplier_return", r.id, "supplier")
        _ref(ds, c, "product", r.product, "supplier_return", r.id, "product")
        _ref(ds, c, "location", r.location, "supplier_return", r.id, "location")


def _lanes(ds: Dataset, c: _Collector) -> None:
    cold = {p.id for p in ds.products if p.cold_chain}
    for ln in ds.lanes:
        if cold and ln.planning_mode.mode is not TransportMode.REEFER:
            if ds.location_type(ln.origin) is LocationType.SUPPLIER:
                goes = {pu.product for pu in ds.purchasing_sources if pu.supplier == ln.origin
                        and pu.location == ln.destination}
            else:
                goes = set(ln.products or []) or ({d.product for d in ds.demand if d.location == ln.destination}
                                                  | {lp.product for lp in ds.location_products
                                                     if lp.location == ln.destination})
            chilled = sorted(p for p in goes & cold if ln.carries(p))
            if chilled:
                c.add("COLD_CHAIN_LANE", "lane", ln.id,
                      f"Carries {', '.join(chilled[:3])}{'…' if len(chilled) > 3 else ''}, kept chilled, but is planned "
                      f"as {ln.planning_mode.mode.value.replace('_', ' ')}",
                      "Plan the route as a refrigerated truck", "modes")
        per_kg = any(m.cost_per_kg > 0 or m.vehicle_capacity_kg for m in ln.modes)
        per_m3 = any(m.cost_per_m3 > 0 or m.vehicle_capacity_m3 for m in ln.modes)
        if not (per_kg or per_m3):
            continue
        if ds.location_type(ln.origin) is LocationType.SUPPLIER:
            # a supplier lane only carries what is bought from that supplier for the destination
            prods = sorted({pu.product for pu in ds.purchasing_sources
                            if pu.supplier == ln.origin and pu.location == ln.destination and ln.carries(pu.product)})
        else:
            prods = ln.products or sorted({d.product for d in ds.demand if d.location == ln.destination} |
                                          {lp.product for lp in ds.location_products if lp.location == ln.destination})
        for pid in prods:
            p = ds.product_by_id.get(pid)
            if p is None:
                continue
            if per_kg and p.weight_kg is None:
                c.add("LANE_WEIGHT_MISSING", "product", pid,
                      f"Lane {ln.id} is costed or capped by weight but {pid} has no weight_kg",
                      "Enter the gross weight per base unit", "weight_kg")
            if per_m3 and p.volume_m3 is None:
                c.add("LANE_WEIGHT_MISSING", "product", pid,
                      f"Lane {ln.id} is costed or capped by volume but {pid} has no volume_m3",
                      "Enter the volume per base unit", "volume_m3")


def _policies(ds: Dataset, c: _Collector) -> None:
    for lp in ds.location_products:
        oid = f"{lp.location}/{lp.product}"
        ss = lp.safety_stock
        if ss.method is not SafetyStockMethod.NONE and lp.safety_time_days > 0:
            c.add("SS_AND_SAFETY_TIME", "location_product", oid,
                  "Safety stock and safety time are both set", "Use one buffer mechanism")
        if ss.method in (SafetyStockMethod.SERVICE_LEVEL, SafetyStockMethod.FILL_RATE) and ss.demand_cv is None:
            c.add("SS_NO_VARIABILITY", "location_product", oid,
                  "Statistical safety stock needs the demand variability (demand_cv)",
                  "Enter the weekly forecast-error CV, or use days_of_supply", "safety_stock.demand_cv")


def _consumption_gaps(ds: Dataset, c: _Collector, end: date) -> None:
    """S/4 guide §5.4 and the double-demand pitfall: forecasts dated on single days (no period) further apart than the
    consumption windows reach leave days on which a sales order can consume nothing, so the order and the forecast
    it should have eaten are both planned. An order on day t reaches a forecast dated f covering ``span`` days when
    f − forward ≤ t ≤ f + span − 1 + backward; a day between the first and last forecast that no forecast reaches
    is a gap."""
    by_node: dict[tuple[str, str], list] = {}
    for d in ds.demand:
        if d.kind is DemandKind.FORECAST and d.qty > 0 and ds.location_type(d.location) is not None:
            by_node.setdefault((d.location, d.product), []).append(d)
    for node in sorted(by_node):
        lp = ds.demand_lp(node)
        if lp.strategy not in (Strategy.MTS_CONSUME, Strategy.ATO) or len(by_node[node]) < 2:
            continue
        back, fwd = int(lp.consumption_backward_days), int(lp.consumption_forward_days)
        reach = sorted((d.date - timedelta(days=fwd), d.date + timedelta(days=max(1, d.period_days or 1) - 1 + back))
                       for d in by_node[node])
        covered = reach[0][1]
        for lo, hi in reach[1:]:
            if lo > covered + timedelta(days=1) and covered < end:
                first, last = covered + timedelta(days=1), lo - timedelta(days=1)
                c.add("CONSUMPTION_GAP", "location_product", f"{node[0]}/{node[1]}",
                      f"A sales order for {node[1]} at {node[0]} dated {first.isoformat()}"
                      + (f" to {last.isoformat()}" if last > first else "")
                      + f" can reach no forecast with consumption windows of {back} days back and {fwd} forward, "
                      "so it is planned on top of the forecast",
                      "Give each forecast the period it covers (period days), or widen the consumption windows to "
                      "at least half the spacing of the forecasts", "consumption_backward_days")
                break
            covered = max(covered, hi)


def _demand(ds: Dataset, c: _Collector) -> None:
    s = ds.settings
    end = s.planning_start + timedelta(days=s.horizon_days)
    past = outside = 0
    mto_fc: set[tuple[str, str]] = set()
    for d in ds.demand:
        if d.date < s.planning_start:
            past += 1
        elif d.date >= end:
            outside += 1
        lp = ds.demand_lp((d.location, d.product)) if ds.location_type(d.location) is not None else None
        if lp and lp.strategy is Strategy.MTO and d.kind is DemandKind.FORECAST:
            mto_fc.add((d.location, d.product))
    if past:
        c.add("DEMAND_PAST_DUE", "demand", "*", f"{past} demand records are before planning start",
              "They are planned as backlog due today")
    if outside:
        c.add("DEMAND_OUTSIDE_HORIZON", "demand", "*", f"{outside} demand records are after the end of the plan",
              "Lengthen the plan (Company settings → horizon days) to plan them")
    _consumption_gaps(ds, c, end)
    for loc, prod in sorted(mto_fc):
        c.add("MTO_WITH_FORECAST", "location_product", f"{loc}/{prod}",
              "Forecast exists but the strategy is MTO", "Use MTS_CONSUME or ATO to pre-plan")
    fc = {(d.location, d.product) for d in ds.demand if d.kind is DemandKind.FORECAST}
    for loc, prod in sorted(fc):
        if ds.location_type(loc) in (None, LocationType.CUSTOMER):
            continue
        below = sorted(x for x in _served_customers(ds, loc, prod) if (x, prod) in fc)
        if below:
            c.add("FORECAST_TWICE", "demand", f"{loc}/{prod}",
                  f"{prod} has a forecast at {loc} and at {', '.join(below)}, which {loc} supplies: the plan makes "
                  "both", f"Right if {loc} also sells {prod} itself (a trade counter). If not, the same sales are "
                  f"counted twice: remove the forecast at {loc}, and give its sales their customer")
    made = ds.forecasting.released_inputs
    if made and any(d.released for d in ds.demand) and made != ds.forecast_inputs():
        c.add("FORECAST_INPUTS_CHANGED", "demand", "*",
              "Demand events, new-product rules, overrides or forecast settings changed after the forecast was last "
              "used in the plan: the plan does not have them yet",
              "Demand → Forecast: recalculate it and press Use this forecast in the supply plan")


def _served_customers(ds: Dataset, loc: str, prod: str) -> set[str]:
    """The customer places a product reaches from ``loc`` along the routes that carry it."""
    out: set[str] = set()
    seen, level = {loc}, [loc]
    while level:
        nxt: list[str] = []
        for ln in ds.lanes:
            if ln.origin not in level or ln.destination in seen or (ln.products and prod not in ln.products):
                continue
            seen.add(ln.destination)
            if ds.location_type(ln.destination) is LocationType.CUSTOMER:
                out.add(ln.destination)
            else:
                nxt.append(ln.destination)
        level = nxt
    return out


def _forecasting(ds: Dataset, c: _Collector) -> None:
    s = ds.settings
    end = s.planning_start + timedelta(days=s.horizon_days)
    late = sum(1 for h in ds.history if h.date >= s.planning_start)
    if late:
        c.add("HISTORY_AFTER_START", "history", "*", f"{late} history rows are on or after planning start",
              "History ends the day before planning starts; move planning start or drop those rows")
    with_history = {(h.location, h.product) for h in ds.history if h.date < s.planning_start and h.qty > 0}
    npi_keys = Counter((n.location, n.product) for n in ds.npi)
    for (loc, prod), k in npi_keys.items():
        if k > 1:
            c.add("NPI_DUPLICATE", "npi", f"{loc}/{prod}", f"{k} NPI rules for {prod} at {loc}; the last one wins",
                  "Keep one rule per product and place")
    for n in ds.npi:
        like = (n.like_location or n.location, n.like_product)
        if like not in with_history:
            c.add("NPI_LIKE_WITHOUT_HISTORY", "npi", f"{n.location}/{n.product}",
                  f"{like[1]} has no sales history at {like[0]}: the NPI forecast will be zero",
                  "Pick a like product with history, or set like_location", "like_product")
    for o in ds.overrides:
        oid = f"{o.location}/{o.product}@{o.date.isoformat()}"
        if not s.planning_start <= o.date < end:
            c.add("OVERRIDE_OUTSIDE_HORIZON", "override", oid, "The override date is outside the plan's dates",
                  "Move it inside the plan or delete it", "date")
        elif (o.location, o.product) not in with_history and (o.location, o.product) not in npi_keys:
            c.add("OVERRIDE_WITHOUT_FORECAST", "override", oid,
                  f"No history or NPI rule for {o.product} at {o.location}, so there is no forecast to adjust",
                  "Add history, add an NPI rule, or enter the demand as a forecast record")


def _graph(ds: Dataset, c: _Collector) -> None:
    g = build_graph(ds)
    for cyc in g.cycles:
        names = " → ".join(f"{p}@{loc}" for loc, p in cyc)
        c.add("BOM_CYCLE", "network", cyc[0][0], f"Circular sourcing: {names}",
              "Restrict lane products or fix the BOM so supply flows one way")
    # which nodes will receive requirements?
    has_req = {(d.location, d.product) for d in ds.demand}
    has_req |= {node for node in g.nodes if g.consumers.get(node)}
    # a co-product comes out of another product's run: that is its supply, even with no source of its own
    co_made = {(ps.location, co.product) for ps in ds.production_sources for co in ps.co_products}
    for node in g.nodes:
        loc, prod = node
        if ds.location_type(loc) not in STOCKING_LOCATION_TYPES | {LocationType.CUSTOMER}:
            continue
        lp = ds.location_product_by_key.get(node)
        if node not in has_req:
            continue
        if lp is None and ds.location_type(loc) is not LocationType.CUSTOMER:
            c.add("LOCATION_PRODUCT_DEFAULTED", "location_product", f"{loc}/{prod}",
                  "No stock or ordering rules here yet: ordered exactly as needed, with no safety stock and nothing on hand",
                  "Enter its stock and ordering rules (Set up → the product, or Planning policies)")
        if not g.options.get(node) and node not in co_made:
            onhand = lp.on_hand if lp else 0.0
            proc = lp.procurement.value if lp else "any"
            limited = {"make": " Its procurement type allows only making it here.",
                       "external": " Its procurement type allows only buying it or shipping it in."}.get(proc, "")
            blocked = sorted(pu.id for pu in ds.purchasing_sources
                             if pu.location == loc and pu.product == prod and ds.source_blocked(pu))
            c.add("NO_SOURCE", "location_product", f"{loc}/{prod}",
                  (f"{prod} at {loc} is needed but its only purchasing sources are blocked ({', '.join(blocked)})"
                   if blocked else
                   f"{prod} at {loc} is needed but has no way to be supplied: it is not made, bought or shipped there")
                  + (f" (only {onhand:g} on hand)" if onhand else "") + ("." + limited if limited else ""),
                  "Say how it gets there: made there, bought from a supplier, or shipped from another place (Set up → the product)"
                  + ("; or change its procurement type" if limited else ""))
    # quotas
    for node, opts in g.options.items():
        q = [o.quota for o in opts if o.quota is not None]
        if q and abs(sum(q) - 1.0) > 1e-6:
            c.add("QUOTA_SUM", "location_product", f"{node[0]}/{node[1]}",
                  f"Quotas sum to {sum(q):.2f}; they are normalised", "Make the quotas add up to 100%")
    # shelf life vs lead time (purchased / transferred items with long pipelines)
    from ..plan.leadtime import nominal_lead_time_days  # local import: avoid cycle at module load

    for node, opts in g.options.items():
        prod = ds.product_by_id.get(node[1])
        if not prod or not prod.shelf_life_days or not opts:
            continue
        lt = nominal_lead_time_days(ds, opts[0])
        if lt is not None and lt > prod.shelf_life_days:
            c.add("SHELF_LIFE_VS_LEAD_TIME", "location_product", f"{node[0]}/{node[1]}",
                  f"Lead time {lt:.0f} d exceeds shelf life {prod.shelf_life_days} d",
                  "Shorten the pipeline or source closer")


def _movements(ds: Dataset, c: _Collector) -> None:
    if not ds.movements:
        return
    from ..actuals.stock import stock_rows, unmatched   # local: actuals imports the model, not the gate
    for row in stock_rows(ds, ds.settings.planning_start):
        oid = f"{row.location}/{row.product}"
        if row.movement_stock is not None and abs(row.difference) > 1e-6:
            c.add("STOCK_NOT_SYNCED", "location_product", oid,
                  f"On-hand {row.master_on_hand:,.2f} but the journal says {row.planning_stock or 0.0:,.2f} usable",
                  "Roll forward (or sync stock) so on-hand is derived from the movements", "on_hand")
        if row.expired > 1e-6:
            c.add("STOCK_EXPIRED", "location_product", oid,
                  f"{row.expired:,.2f} in batches past their expiry date",
                  "Scrap them (Execution → Stock), or block them while you decide")
        if row.negative_on is not None:
            c.add("NEGATIVE_STOCK", "location_product", oid,
                  f"Stock goes negative on {row.negative_on.isoformat()}",
                  "A receipt is missing or posted late; post it, or a count adjustment")
    known = {m.id: m for m in ds.movements}
    batches = {(b.product, b.id) for b in ds.batches}
    for m in ds.movements:
        prod = ds.product_by_id.get(m.product)
        if m.reversal_of and m.reversal_of not in known:
            c.add("REVERSAL_UNKNOWN", "movement", m.id, f"Takes back {m.reversal_of}, which is not in the journal",
                  "Fix the movement it reverses", "reversal_of")
        if m.batch and (m.product, m.batch) not in batches:
            c.add("BATCH_UNKNOWN", "movement", m.id, f"Batch {m.batch} of {m.product} has no batch record: its "
                  "expiry date is not known", "Add the batch with its expiry date", "batch")
        if prod and prod.serial_numbers and m.type.value not in ("adjustment", "status") and m.serials \
                and len(m.serials) != round(abs(m.qty)):
            c.add("SERIALS_COUNT", "movement", m.id, f"{len(m.serials)} serial numbers for {m.qty:g} units",
                  "Give one serial number per unit", "serials")
    for mid in unmatched(ds):
        c.add("MOVEMENT_REF_UNKNOWN", "movement", mid, "The reference matches no receipt, sales order or closed order",
              "Fix the reference, or leave it empty for an unplanned movement", "reference")
