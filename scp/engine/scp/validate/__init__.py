"""Readiness gate — master-data checks before any plan runs (S/4 guide §3 "master data readiness
gate": most "the system planned it wrong" incidents are master-data defects).

Every rule has a stable code, a severity, the offending object, and a fix hint. Errors block
planning; warnings are shown with the plan. Rules are listed in :data:`RULES` so the UI and the
docs can enumerate them, and each one has a positive and negative test.
"""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ..model import (
    Dataset, DemandKind, LocationType, SafetyStockMethod, Strategy,
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
    "STOCK_AT_CUSTOMER": ("warning", "Stock maintained at a customer location is not planned"),
    "RESOURCE_UNUSED": ("warning", "Resource not used by any operation"),
    "LOCATION_PRODUCT_DEFAULTED": ("warning", "Planning node without a location-product: defaults used"),
    "SHELF_LIFE_VS_LEAD_TIME": ("warning", "Replenishment lead time exceeds shelf life"),
    "HISTORY_AFTER_START": ("warning", "Sales history on or after planning start is not used"),
    "NPI_LIKE_WITHOUT_HISTORY": ("warning", "NPI like product has no sales history at that location"),
    "NPI_DUPLICATE": ("warning", "More than one NPI rule for the same location-product"),
    "OVERRIDE_OUTSIDE_HORIZON": ("warning", "Consensus override outside the forecast horizon is ignored"),
    "OVERRIDE_WITHOUT_FORECAST": ("warning", "Consensus override for a series with no history or NPI rule"),
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
    order = {"error": 0, "warning": 1}
    c.issues.sort(key=lambda i: (order[i.severity], i.code, i.object_type, i.object_id))
    return c.issues


def has_errors(issues: list[Issue]) -> bool:
    return any(i.severity == "error" for i in issues)


# ---------------------------------------------------------------------------------------------
def _duplicates(ds: Dataset, c: _Collector) -> None:
    groups = {
        "calendar": ds.calendars, "location": ds.locations, "product": ds.products,
        "resource": ds.resources, "production_source": ds.production_sources,
        "purchasing_source": ds.purchasing_sources, "lane": ds.lanes, "receipt": ds.receipts,
    }
    for typ, items in groups.items():
        for oid, n in Counter(i.id for i in items).items():
            if n > 1:
                c.add("DUP_ID", typ, oid, f"{typ} id '{oid}' is used {n} times", "Ids must be unique per type")
    for (loc, prod), n in Counter((lp.location, lp.product) for lp in ds.location_products).items():
        if n > 1:
            c.add("DUP_LOCATION_PRODUCT", "location_product", f"{loc}/{prod}",
                  f"{prod} at {loc} is maintained {n} times", "Keep exactly one planning record")


def _ref(ds: Dataset, c: _Collector, kind: str, value: str | None, typ: str, oid: str, field: str) -> bool:
    if value is None:
        return True
    index = {"location": ds.location_by_id, "product": ds.product_by_id,
             "calendar": ds.calendar_by_id, "resource": ds.resource_by_id}[kind]
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
        for op in ps.operations:
            _ref(ds, c, "resource", op.resource, "production_source", ps.id, f"operations[{op.seq}].resource")
            _ref(ds, c, "resource", op.labor_resource, "production_source", ps.id,
                 f"operations[{op.seq}].labor_resource")
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
    for i, co in enumerate(ds.changeovers):
        _ref(ds, c, "resource", co.resource, "changeover", f"#{i}", "resource")
    for r in ds.receipts:
        if _ref(ds, c, "location", r.location, "receipt", r.id, "location"):
            _loc_type(ds, c, r.location, STOCKING_LOCATION_TYPES, "receipt", r.id, "location",
                      "receipts land at stocking locations")
        _ref(ds, c, "product", r.product, "receipt", r.id, "product")


def _currency(ds: Dataset, c: _Collector) -> None:
    s = ds.settings
    for pu in ds.purchasing_sources:
        cur = pu.currency
        if cur and cur != s.currency and cur not in s.fx_rates:
            c.add("FX_MISSING", "purchasing_source", pu.id, f"No exchange rate for {cur}",
                  f"Add settings.fx_rates['{cur}'] ({s.currency} per 1 {cur})", "currency")


def _calendars(ds: Dataset, c: _Collector) -> None:
    from ..time import WorkCalendar

    s = ds.settings
    for cal in ds.calendars:
        wc = WorkCalendar(cal)
        if wc.workdays_between(s.planning_start, s.planning_start + timedelta(days=s.horizon_days)) == 0:
            c.add("CALENDAR_NO_WORKDAY_IN_HORIZON", "calendar", cal.id,
                  "No working day inside the planning horizon", "Check weekdays and holidays")


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
            used.add(op.resource)
            if op.labor_resource:
                used.add(op.labor_resource)
            for rid in (op.resource, op.labor_resource):
                r = ds.resource_by_id.get(rid) if rid else None
                if r is not None and r.location != ps.location:
                    c.add("RESOURCE_WRONG_LOCATION", "production_source", ps.id,
                          f"Operation {op.seq} uses {rid} located at {r.location}, not {ps.location}",
                          "Use a resource of the producing plant", f"operations[{op.seq}]")
        if not _covers(ps.valid_from, ps.valid_to, s.planning_start, end):
            c.add("SOURCE_NOT_VALID_IN_HORIZON", "production_source", ps.id,
                  "Validity dates do not cover the whole horizon; requirements outside are unsourced",
                  "Extend valid_from/valid_to or add another source")
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
                  "Validity dates do not cover the whole horizon", "Extend validity or add another source")


def _lanes(ds: Dataset, c: _Collector) -> None:
    for ln in ds.lanes:
        per_kg = any(m.cost_per_kg > 0 or m.vehicle_capacity_kg for m in ln.modes)
        per_m3 = any(m.cost_per_m3 > 0 or m.vehicle_capacity_m3 for m in ln.modes)
        if not (per_kg or per_m3):
            continue
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
        lp = ds.location_product_by_key.get((d.location, d.product))
        if lp and lp.strategy is Strategy.MTO and d.kind is DemandKind.FORECAST:
            mto_fc.add((d.location, d.product))
    if past:
        c.add("DEMAND_PAST_DUE", "demand", "*", f"{past} demand records are before planning start",
              "They are planned as backlog due today")
    if outside:
        c.add("DEMAND_OUTSIDE_HORIZON", "demand", "*", f"{outside} demand records are beyond the horizon",
              "Extend the horizon to plan them")
    for loc, prod in sorted(mto_fc):
        c.add("MTO_WITH_FORECAST", "location_product", f"{loc}/{prod}",
              "Forecast exists but the strategy is MTO", "Use MTS_CONSUME or ATO to pre-plan")


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
                  "Keep one rule per location-product")
    for n in ds.npi:
        like = (n.like_location or n.location, n.like_product)
        if like not in with_history:
            c.add("NPI_LIKE_WITHOUT_HISTORY", "npi", f"{n.location}/{n.product}",
                  f"{like[1]} has no sales history at {like[0]}: the NPI forecast will be zero",
                  "Pick a like product with history, or set like_location", "like_product")
    for o in ds.overrides:
        oid = f"{o.location}/{o.product}@{o.date.isoformat()}"
        if not s.planning_start <= o.date < end:
            c.add("OVERRIDE_OUTSIDE_HORIZON", "override", oid, "The override date is outside the horizon",
                  "Move it into the planning horizon or delete it", "date")
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
    for node in g.nodes:
        loc, prod = node
        if ds.location_type(loc) not in STOCKING_LOCATION_TYPES | {LocationType.CUSTOMER}:
            continue
        lp = ds.location_product_by_key.get(node)
        if node not in has_req:
            continue
        if lp is None and ds.location_type(loc) is not LocationType.CUSTOMER:
            c.add("LOCATION_PRODUCT_DEFAULTED", "location_product", f"{loc}/{prod}",
                  "No planning record: L4L, no safety stock, zero stock assumed",
                  "Maintain a location-product for this node")
        if not g.options.get(node):
            onhand = lp.on_hand if lp else 0.0
            c.add("NO_SOURCE", "location_product", f"{loc}/{prod}",
                  f"{prod} at {loc} has requirements but no production, purchasing or lane source"
                  + (f" (only {onhand:g} on hand)" if onhand else ""),
                  "Add a production source, purchasing source or inbound lane")
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
