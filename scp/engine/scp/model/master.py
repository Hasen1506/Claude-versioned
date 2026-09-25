"""Master data — the user's network. Mirrors the S/4 object catalogue (guide §3.1), scaled to
small and mid-sized organisations. Object-local invariants are enforced here; cross-object
(referential) checks live in :mod:`scp.validate` so that *all* problems are reported at once.
"""
from __future__ import annotations

from datetime import date

from pydantic import Field, field_validator, model_validator

from .common import (
    BucketSize, Id, LocationType, LotSizePolicy, Model, MrpType, ProductType, Ref, ResourceKind,
    SafetyStockMethod, Strategy, TransportMode, Unit,
)


# --------------------------------------------------------------------------------------------
# Settings & calendars
# --------------------------------------------------------------------------------------------
class Settings(Model):
    company_name: str = Field("My Company", max_length=120)
    currency: str = Field("INR", min_length=3, max_length=3, description="ISO 4217 company currency")
    planning_start: date = Field(description="First day of the plan ('today' for planning)")
    horizon_days: int = Field(182, ge=7, le=1100, description="Planning horizon length in calendar days")
    bucket: BucketSize = Field(BucketSize.WEEK, description="Reporting / periodic lot-sizing bucket")
    week_start: int = Field(0, ge=0, le=6, description="0 = Monday … 6 = Sunday")
    fx_rates: dict[str, float] = Field(
        default_factory=dict,
        description="Company-currency units per 1 unit of foreign currency, e.g. {'USD': 84.2}")
    wacc: float = Unit("fraction", le=1, default=0.12, description="Weighted average cost of capital, per year")
    holding_spread: float = Unit("fraction", le=1, default=0.08,
                                 description="Storage + insurance + obsolescence on top of WACC, per year")
    default_service_level: float = Unit("fraction", gt=0, lt=1, default=0.95)
    default_calendar: str | None = Ref("calendar", default=None)

    @property
    def carrying_rate(self) -> float:
        """Annual inventory carrying rate = WACC + holding spread (fraction per year)."""
        return self.wacc + self.holding_spread

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @field_validator("fx_rates")
    @classmethod
    def _fx_positive(cls, v: dict[str, float]) -> dict[str, float]:
        out = {}
        for k, rate in v.items():
            if rate <= 0:
                raise ValueError(f"fx rate for {k} must be > 0")
            out[k.upper()] = rate
        return out


class Calendar(Model):
    id: Id
    name: str = ""
    workdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4],
                                description="Working weekdays, 0 = Monday … 6 = Sunday")
    holidays: list[date] = Field(default_factory=list)

    @field_validator("workdays")
    @classmethod
    def _wd(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("a calendar needs at least one working weekday")
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("weekdays must be 0..6")
        return sorted(set(v))


# --------------------------------------------------------------------------------------------
# Locations & products
# --------------------------------------------------------------------------------------------
class Location(Model):
    id: Id
    name: str = ""
    type: LocationType
    region: str = ""
    calendar: str | None = Ref("calendar", default=None)
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    storage_capacity_m3: float | None = Unit("m3", default=None)
    handling_cost_per_unit: float = Unit("money_per_unit", default=0.0,
                                         description="Inbound handling cost per base unit received")


class UomConversion(Model):
    uom: str = Field(min_length=1, max_length=12)
    factor: float = Unit("qty", gt=0, description="Base units in one of this UoM (e.g. 1 CS = 12 EA → 12)")


class Product(Model):
    id: Id
    name: str = ""
    type: ProductType
    base_uom: str = Field("EA", min_length=1, max_length=12)
    conversions: list[UomConversion] = Field(default_factory=list)
    family: str = ""
    weight_kg: float | None = Unit("kg", default=None, description="Gross weight per base unit")
    volume_m3: float | None = Unit("m3", default=None, description="Volume per base unit")
    shelf_life_days: int | None = Field(None, gt=0)
    standard_cost: float | None = Unit("money_per_unit", default=None,
                                       description="Override for the computed cost roll-up")
    price: float | None = Unit("money_per_unit", default=None, description="Default selling price")
    setup_group: str | None = Field(None, max_length=40,
                                    description="Sequence-dependent setup family (colour, allergen, grade…)")

    @field_validator("conversions")
    @classmethod
    def _unique_uom(cls, v: list[UomConversion]) -> list[UomConversion]:
        names = [c.uom for c in v]
        if len(names) != len(set(names)):
            raise ValueError("duplicate UoM in conversions")
        return v


class LotSizing(Model):
    policy: LotSizePolicy = LotSizePolicy.L4L
    fixed_qty: float | None = Unit("qty", gt=0, default=None, description="FIXED: lot size")
    periods: int | None = Field(None, ge=1, le=52, description="POQ: number of buckets each order covers")
    min_qty: float = Unit("qty", default=0.0, description="Minimum lot size")
    max_qty: float | None = Unit("qty", gt=0, default=None, description="Maximum lot size (orders are split)")
    rounding_qty: float | None = Unit("qty", gt=0, default=None, description="Round lots up to a multiple")
    ordering_cost: float = Unit("money", default=0.0, description="Fixed cost per order (EOQ)")

    @model_validator(mode="after")
    def _params(self) -> LotSizing:
        if self.policy is LotSizePolicy.FIXED and self.fixed_qty is None:
            raise ValueError("FIXED lot sizing needs fixed_qty")
        if self.policy is LotSizePolicy.POQ and self.periods is None:
            raise ValueError("POQ lot sizing needs periods")
        if self.max_qty is not None and self.max_qty < self.min_qty:
            raise ValueError("max_qty must be ≥ min_qty")
        return self


class SafetyStockPolicy(Model):
    method: SafetyStockMethod = SafetyStockMethod.NONE
    qty: float | None = Unit("qty", default=None, description="fixed: safety stock quantity")
    days: float | None = Unit("days", default=None, description="days_of_supply: forward coverage")
    service_level: float | None = Unit("fraction", gt=0, lt=1, default=None,
                                       description="service_level / fill_rate target (default: settings)")
    demand_cv: float | None = Unit("fraction", le=5, default=None,
                                   description="Coefficient of variation of WEEKLY demand (forecast error)")
    review_period_days: float = Unit("days", default=0.0, description="Periodic review interval R")

    @model_validator(mode="after")
    def _params(self) -> SafetyStockPolicy:
        m = self.method
        if m is SafetyStockMethod.FIXED and self.qty is None:
            raise ValueError("fixed safety stock needs qty")
        if m is SafetyStockMethod.DAYS_OF_SUPPLY and not self.days:
            raise ValueError("days_of_supply safety stock needs days > 0")
        return self


class LocationProduct(Model):
    """How one product is planned at one location (≈ S/4 MARC, MRP views 1–4)."""

    location: str = Ref("location")
    product: str = Ref("product")
    strategy: Strategy = Strategy.MTS_CONSUME
    mrp_type: MrpType = MrpType.DETERMINISTIC
    on_hand: float = Unit("qty", default=0.0, description="Unrestricted stock at planning start")
    unit_cost: float | None = Unit("money_per_unit", default=None, description="Valuation override")
    lot_sizing: LotSizing = Field(default_factory=LotSizing)
    safety_stock: SafetyStockPolicy = Field(default_factory=SafetyStockPolicy)
    safety_time_days: float = Unit("days", default=0.0, description="Plan receipts this many days early")
    reorder_point: float | None = Unit("qty", default=None, description="reorder_point MRP type trigger")
    max_stock: float | None = Unit("qty", default=None, description="MIN_MAX target / excess threshold")
    planning_time_fence_days: float = Unit("days", default=0.0,
                                           description="No new proposals inside this fence (firming type 1)")
    gr_processing_days: float = Unit("days", default=0.0, description="Goods-receipt / putaway time")
    consumption_backward_days: float = Unit("days", default=7.0)
    consumption_forward_days: float = Unit("days", default=7.0)
    holding_rate: float | None = Unit("fraction", le=2, default=None,
                                      description="Annual carrying rate override (default: WACC + spread)")
    ddmrp_buffer: bool = Field(False, description="Strategic decoupling point: DDMRP buffer positioned here")
    max_service_days: float | None = Unit(
        "days", default=None,
        description="MEIO: the longest outbound service time this node may quote (empty = no limit, or the "
                    "customer service time where it faces demand)")

    @model_validator(mode="after")
    def _params(self) -> LocationProduct:
        if self.mrp_type is MrpType.REORDER_POINT and self.reorder_point is None:
            raise ValueError("reorder_point MRP type needs reorder_point")
        if self.lot_sizing.policy is LotSizePolicy.MIN_MAX and self.max_stock is None:
            raise ValueError("MIN_MAX lot sizing needs max_stock")
        return self


# --------------------------------------------------------------------------------------------
# Capacity & production
# --------------------------------------------------------------------------------------------
class Resource(Model):
    """A work center: machine, line, labour pool or tool (≈ S/4 work center / PP-DS resource)."""

    id: Id
    name: str = ""
    location: str = Ref("location")
    kind: ResourceKind = ResourceKind.MACHINE
    units: int = Field(1, ge=1, le=10_000, description="Parallel machines, or headcount for labour")
    shifts_per_day: float = Field(1.0, gt=0, le=4)
    hours_per_shift: float = Unit("hours", gt=0, le=24, default=8.0)
    efficiency: float = Unit("fraction", gt=0, le=1, default=0.85,
                             description="OEE / utilisation: share of shift hours that are productive")
    calendar: str | None = Ref("calendar", default=None, description="Override the location calendar")
    cost_per_hour: float = Unit("money_per_hour", default=0.0)
    overtime_hours_per_day: float = Unit("hours", default=0.0, description="Max overtime per unit per workday")
    overtime_cost_per_hour: float = Unit("money_per_hour", default=0.0)
    finite: bool = Field(True, description="Constrain plans by this resource's capacity")

    @model_validator(mode="after")
    def _day(self) -> Resource:
        if self.shifts_per_day * self.hours_per_shift + self.overtime_hours_per_day > 24 + 1e-9:
            raise ValueError("shifts × hours per shift + overtime exceeds 24 h per day")
        return self

    @property
    def hours_per_workday_per_unit(self) -> float:
        """Productive hours one unit (machine / person) delivers on a working day."""
        return self.shifts_per_day * self.hours_per_shift * self.efficiency

    @property
    def hours_per_workday(self) -> float:
        return self.hours_per_workday_per_unit * self.units


class BomItem(Model):
    product: str = Ref("product")
    qty: float = Unit("qty", gt=0, description="Quantity per output_qty of the parent")
    scrap: float = Unit("fraction", lt=1, default=0.0,
                        description="Component scrap: share of the issued quantity lost (issue = need ÷ (1 − scrap))")
    operation: int | None = Field(None, ge=1, description="Operation seq that consumes it (default: first)")


class Operation(Model):
    seq: int = Field(ge=1)
    name: str = ""
    resource: str = Ref("resource")
    setup_hours: float = Unit("hours", default=0.0, description="Per order")
    run_hours_per_unit: float = Unit("hours", default=0.0, description="Machine hours per output base unit")
    labor_resource: str | None = Ref("resource", default=None)
    labor_hours_per_unit: float = Unit("hours", default=0.0, description="Worker hours per output unit")
    queue_workdays: float = Unit("workdays", default=0.0, description="Wait + move time after the operation")
    parallel_units: int | None = Field(None, ge=1, description="Resource units one order may run on in parallel "
                                                                "(default: all units of the resource)")

    @model_validator(mode="after")
    def _labor(self) -> Operation:
        if self.labor_hours_per_unit > 0 and not self.labor_resource:
            raise ValueError("labor_hours_per_unit needs a labor_resource")
        return self


class ProductionSource(Model):
    """How to make a product at a plant: BOM + routing (≈ S/4 production version)."""

    id: Id
    location: str = Ref("location")
    product: str = Ref("product")
    output_qty: float = Unit("qty", gt=0, default=1.0, description="Base quantity the BOM refers to")
    components: list[BomItem] = Field(default_factory=list)
    operations: list[Operation] = Field(default_factory=list)
    assembly_scrap: float = Unit("fraction", lt=1, default=0.0,
                                 description="Share of started output lost (start = good ÷ (1 − scrap))")
    fixed_lead_time_workdays: float | None = Unit(
        "workdays", default=None, description="Override the routing-derived production lead time")
    min_lot: float = Unit("qty", default=0.0)
    max_lot: float | None = Unit("qty", gt=0, default=None)
    conversion_cost_per_unit: float = Unit("money_per_unit", default=0.0,
                                           description="Cost not captured by resource rates (energy, overhead)")
    priority: int = Field(1, ge=1, le=99, description="Lower wins when several sources exist")
    quota: float | None = Unit("fraction", default=None, le=1, description="Share of requirements")
    valid_from: date | None = None
    valid_to: date | None = None

    @model_validator(mode="after")
    def _structure(self) -> ProductionSource:
        seqs = [o.seq for o in self.operations]
        if len(seqs) != len(set(seqs)):
            raise ValueError("duplicate operation seq")
        comps = [c.product for c in self.components]
        if len(comps) != len(set(comps)):
            raise ValueError("a component appears twice in the BOM — merge the lines")
        if self.product in comps:
            raise ValueError("a product cannot be its own component")
        for c in self.components:
            if c.operation is not None and c.operation not in seqs:
                raise ValueError(f"component {c.product} references unknown operation {c.operation}")
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to before valid_from")
        if self.max_lot is not None and self.max_lot < self.min_lot:
            raise ValueError("max_lot must be ≥ min_lot")
        self.operations.sort(key=lambda o: o.seq)
        return self


# --------------------------------------------------------------------------------------------
# Sourcing & transport
# --------------------------------------------------------------------------------------------
class PurchasingSource(Model):
    """Who sells us a product, at what price and lead time (≈ info record + source list + quota)."""

    id: Id
    supplier: str = Ref("location", description="A location of type supplier")
    product: str = Ref("product")
    location: str = Ref("location", description="Receiving location")
    price: float = Unit("money_per_unit", description="Price per base unit in `currency`")
    currency: str | None = Field(None, min_length=3, max_length=3, description="Default: company currency")
    duty_rate: float = Unit("fraction", le=5, default=0.0, description="Import duty/tariff on price")
    ordering_cost: float = Unit("money", default=0.0, description="Fixed cost per purchase order")
    moq: float = Unit("qty", default=0.0, description="Minimum order quantity")
    rounding_qty: float | None = Unit("qty", gt=0, default=None, description="Pack / pallet multiple")
    lead_time_days: float = Unit("days", description="Supplier processing: PO to dispatch (transit is on the lane)")
    lead_time_std_days: float = Unit("days", default=0.0, description="Std deviation of the lead time")
    capacity_per_week: float | None = Unit("qty", gt=0, default=None, description="Supplier capacity")
    priority: int = Field(1, ge=1, le=99)
    quota: float | None = Unit("fraction", default=None, le=1)
    valid_from: date | None = None
    valid_to: date | None = None

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class LaneMode(Model):
    mode: TransportMode = TransportMode.TRUCK_FTL
    transit_days: float = Unit("days")
    transit_std_days: float = Unit("days", default=0.0)
    cost_per_unit: float = Unit("money_per_unit", default=0.0)
    cost_per_kg: float = Unit("money_per_kg", default=0.0)
    cost_per_m3: float = Unit("money_per_m3", default=0.0)
    cost_per_shipment: float = Unit("money", default=0.0, description="Fixed cost per dispatch")
    vehicle_capacity_kg: float | None = Unit("kg", gt=0, default=None)
    vehicle_capacity_m3: float | None = Unit("m3", gt=0, default=None)
    capacity_units_per_week: float | None = Unit("qty", gt=0, default=None)
    default: bool = Field(False, description="Mode used by the MRP heuristic (else the first mode)")


class TransportLane(Model):
    id: Id
    origin: str = Ref("location")
    destination: str = Ref("location")
    products: list[str] | None = Field(None, json_schema_extra={"x-ref": "product"},
                                       description="Products carried; empty = all")
    modes: list[LaneMode] = Field(min_length=1)
    priority: int = Field(1, ge=1, le=99)
    quota: float | None = Unit("fraction", default=None, le=1)

    @model_validator(mode="after")
    def _ends(self) -> TransportLane:
        if self.origin == self.destination:
            raise ValueError("lane origin and destination are the same")
        if sum(1 for m in self.modes if m.default) > 1:
            raise ValueError("at most one default mode per lane")
        return self

    @property
    def planning_mode(self) -> LaneMode:
        for m in self.modes:
            if m.default:
                return m
        return self.modes[0]

    def carries(self, product: str) -> bool:
        return not self.products or product in self.products
