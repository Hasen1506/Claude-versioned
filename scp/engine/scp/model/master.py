"""Master data — the user's network. Mirrors the S/4 object catalogue (guide §3.1), scaled to
small and mid-sized organisations. Object-local invariants are enforced here; cross-object
(referential) checks live in :mod:`scp.validate` so that *all* problems are reported at once.
"""
from __future__ import annotations

from datetime import date

from pydantic import Field, field_validator, model_validator

from .common import (
    BucketSize, Id, LocationType, LotSizePolicy, Model, MrpType, ProcurementType, ProductType, Ref, ResourceKind,
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
    capacity_constrained: bool = Field(
        False, description="Plan make orders within the capacity of finite machines and labour: an order that does "
                           "not fit uses an alternative machine, else starts earlier, else finishes later (reported)")

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
            raise ValueError("fixed batches need a batch size (fixed qty)")
        if self.policy is LotSizePolicy.POQ and self.periods is None:
            raise ValueError("periodic ordering needs the number of periods each order covers")
        if self.max_qty is not None and self.max_qty < self.min_qty:
            raise ValueError("the maximum lot must be at least the minimum lot")
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
            raise ValueError("a fixed safety stock needs its quantity")
        if m is SafetyStockMethod.DAYS_OF_SUPPLY and not self.days:
            raise ValueError("safety stock in days of cover needs the number of days")
        return self


class LocationProduct(Model):
    """How one product is planned at one location (≈ S/4 MARC, MRP views 1–4)."""

    location: str = Ref("location")
    product: str = Ref("product")
    mrp_controller: str = Field("", max_length=40, description="Who plans it (MRP controller): filters the worklists")
    procurement: ProcurementType = Field(ProcurementType.ANY,
                                         description="Make here, get from outside (buy or transfer), or either")
    phantom: bool = Field(False, description="Phantom assembly: never stocked; its parts go straight into the parent")
    float_before_workdays: float = Unit("workdays", default=0.0,
                                        description="Scheduling margin: release this many working days before production starts")
    float_after_workdays: float = Unit("workdays", default=0.0,
                                       description="Scheduling margin: working days kept between production end and the due date")
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
            raise ValueError("reorder-point planning needs the reorder point")
        if self.lot_sizing.policy is LotSizePolicy.MIN_MAX and self.max_stock is None:
            raise ValueError("min–max ordering needs the maximum stock")
        return self


# --------------------------------------------------------------------------------------------
# Capacity & production
# --------------------------------------------------------------------------------------------
HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


def hours_of(hhmm: str) -> float:
    h, m = hhmm.split(":")
    return int(h) + int(m) / 60.0


class Shift(Model):
    """One named shift (≈ S/4 shift definition): its clock times, its break and the weekdays it runs."""

    name: str = Field("", max_length=40, description="e.g. Early, Late, Night")
    start: str = Field(pattern=HHMM, description="Start time, HH:MM")
    end: str = Field(pattern=HHMM, description="End time, HH:MM; earlier than the start means it ends the next day")
    break_minutes: float = Unit("minutes", le=720, default=0.0, description="Unpaid break inside the shift")
    break_start: str | None = Field(None, pattern=HHMM, description="When the break starts (default: halfway)")
    weekdays: list[int] | None = Field(None, description="Only on these weekdays, 0 = Monday (empty = every working day)")

    @property
    def length_hours(self) -> float:
        span = (hours_of(self.end) - hours_of(self.start)) % 24.0
        return span or 24.0

    @property
    def net_hours(self) -> float:
        return self.length_hours - self.break_minutes / 60.0

    def runs_on(self, weekday: int) -> bool:
        return not self.weekdays or weekday in self.weekdays

    def windows(self) -> list[tuple[float, float]]:
        """Working windows in hours from the start of the day it begins on (may run past 24)."""
        a = hours_of(self.start)
        b = a + self.length_hours
        brk = self.break_minutes / 60.0
        if brk <= 0:
            return [(a, b)]
        if self.break_start is None:
            bs = a + (self.length_hours - brk) / 2.0
        else:
            bs = a + (hours_of(self.break_start) - a) % 24.0
        return [(x, y) for x, y in ((a, bs), (bs + brk, b)) if y > x + 1e-9]

    @model_validator(mode="after")
    def _fit(self) -> Shift:
        if self.break_minutes / 60.0 >= self.length_hours:
            raise ValueError("the break is as long as the shift")
        if self.break_start is not None and self.break_minutes > 0:
            off = (hours_of(self.break_start) - hours_of(self.start)) % 24.0
            if off + self.break_minutes / 60.0 > self.length_hours + 1e-9:
                raise ValueError("the break must fall inside the shift")
        if self.weekdays is not None and any(d < 0 or d > 6 for d in self.weekdays):
            raise ValueError("weekdays must be 0..6")
        return self


def _day_hours(shifts: list[Shift]) -> float:
    """The most net hours any weekday gets from these shifts."""
    return max((sum(s.net_hours for s in shifts if s.runs_on(d)) for d in range(7)), default=0.0)


class CapacityChange(Model):
    """Capacity that differs for a period (≈ S/4 interval of available capacity): a second shift from
    a date, a machine out for maintenance, a line running slower while it is being run in."""

    valid_from: date
    valid_to: date | None = Field(None, description="Last day it applies (empty = from then on)")
    units: int | None = Field(None, ge=0, le=10_000, description="Machines or people available (0 = shut down)")
    shifts: list[Shift] | None = Field(None, description="Shifts worked in this period instead of the usual ones")
    shifts_per_day: float | None = Field(None, gt=0, le=4, description="Or: how many shifts of the usual length")
    efficiency: float | None = Unit("fraction", gt=0, le=1, default=None)
    note: str = Field("", max_length=120)

    @model_validator(mode="after")
    def _dates(self) -> CapacityChange:
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("the period ends before it starts")
        if self.shifts is not None and _day_hours(self.shifts) > 24 + 1e-9:
            raise ValueError("the shifts add up to more than 24 hours on one day")
        return self

    def covers(self, d: date) -> bool:
        return self.valid_from <= d and (self.valid_to is None or d <= self.valid_to)


class Resource(Model):
    """A work center: machine, line, labour pool or tool (≈ S/4 work center / PP-DS resource)."""

    id: Id
    name: str = ""
    location: str = Ref("location")
    kind: ResourceKind = ResourceKind.MACHINE
    units: int = Field(1, ge=1, le=10_000, description="Parallel machines, or headcount for labour")
    shifts_per_day: float = Field(1.0, gt=0, le=4, description="Used when no named shifts are given")
    hours_per_shift: float = Unit("hours", gt=0, le=24, default=8.0, description="Used when no named shifts are given")
    shifts: list[Shift] = Field(default_factory=list,
                                description="Named shifts with clock times and breaks (replace shifts per day)")
    capacity_changes: list[CapacityChange] = Field(
        default_factory=list, description="Periods with other shifts, units or efficiency (later rows win)")
    efficiency: float = Unit("fraction", gt=0, le=1, default=0.85,
                             description="OEE / utilisation: share of shift hours that are productive")
    calendar: str | None = Ref("calendar", default=None, description="Override the location calendar")
    cost_per_hour: float = Unit("money_per_hour", default=0.0)
    overtime_hours_per_day: float = Unit("hours", default=0.0, description="Max overtime per unit per workday")
    overtime_cost_per_hour: float = Unit("money_per_hour", default=0.0)
    finite: bool = Field(True, description="Constrain plans by this resource's capacity")

    @model_validator(mode="after")
    def _day(self) -> Resource:
        if self.shifts:
            if _day_hours(self.shifts) + self.overtime_hours_per_day > 24 + 1e-9:
                raise ValueError("the shifts and overtime add up to more than 24 hours on one day")
        elif self.shifts_per_day * self.hours_per_shift + self.overtime_hours_per_day > 24 + 1e-9:
            raise ValueError("shifts × hours per shift + overtime exceeds 24 h per day")
        return self

    @property
    def shift_hours_per_workday(self) -> float:
        """Paid clock hours one unit works on a usual working day (the average over the weekdays shifts run)."""
        if not self.shifts:
            return self.shifts_per_day * self.hours_per_shift
        days = [sum(s.net_hours for s in self.shifts if s.runs_on(d)) for d in range(7)]
        worked = [h for h in days if h > 0]
        return sum(worked) / len(worked) if worked else 0.0

    @property
    def hours_per_workday_per_unit(self) -> float:
        """Productive hours one unit (machine / person) delivers on a usual working day."""
        return self.shift_hours_per_workday * self.efficiency

    @property
    def hours_per_workday(self) -> float:
        return self.hours_per_workday_per_unit * self.units


class BomItem(Model):
    product: str = Ref("product")
    qty: float = Unit("qty", gt=0, description="Quantity per output_qty of the parent")
    scrap: float = Unit("fraction", lt=1, default=0.0,
                        description="Component scrap: share of the issued quantity lost (issue = need ÷ (1 − scrap))")
    operation: int | None = Field(None, ge=1, description="Operation seq that consumes it (default: first)")
    fixed_qty: bool = Field(False, description="The quantity is per order, whatever its size (a mould, a fixed charge)")
    valid_from: date | None = Field(None, description="Engineering change: used on orders starting on or after this day")
    valid_to: date | None = Field(None, description="Engineering change: used on orders starting on or before this day")
    change: str = Field("", max_length=40, description="Engineering change number or reason")

    def valid_on(self, d: date) -> bool:
        return (self.valid_from is None or self.valid_from <= d) and (self.valid_to is None or d <= self.valid_to)

    @model_validator(mode="after")
    def _dates(self) -> BomItem:
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("the part stops being used before it starts")
        return self


class CoProduct(Model):
    """Another product the same production run yields (≈ S/4 co-product / by-product)."""

    product: str = Ref("product")
    qty: float = Unit("qty", gt=0, description="Quantity per output_qty of the main product")
    cost_share: float = Unit("fraction", le=1, default=0.0,
                             description="Share of the run's cost it carries (0 = a by-product that carries none)")


class Subcontract(Model):
    """An operation done outside by a supplier (≈ S/4 external operation): no own resource is loaded."""

    supplier: str = Ref("location", description="A location of type supplier")
    workdays: float = Unit("workdays", description="Working days from sending the parts to getting them back")
    cost_per_unit: float = Unit("money_per_unit", default=0.0, description="Price per unit processed")


class Operation(Model):
    seq: int = Field(ge=1)
    name: str = ""
    resource: str | None = Ref("resource", default=None, description="Machine or line (empty only when done outside)")
    setup_hours: float = Unit("hours", default=0.0, description="Per order")
    run_hours_per_unit: float = Unit("hours", default=0.0, description="Machine hours per output base unit")
    labor_resource: str | None = Ref("resource", default=None)
    labor_hours_per_unit: float = Unit("hours", default=0.0, description="Worker hours per output unit")
    queue_workdays: float = Unit("workdays", default=0.0, description="Wait + move time after the operation")
    parallel_units: int | None = Field(None, ge=1, description="Resource units one order may run on in parallel "
                                                                "(default: all units of the resource)")
    scrap: float = Unit("fraction", lt=1, default=0.0,
                        description="Share of the units entering this step that are lost in it")
    send_ahead_qty: float | None = Unit(
        "qty", gt=0, default=None,
        description="Overlap: the next step may start once this many units are done here (empty = when all are)")
    alternatives: list[str] = Field(default_factory=list, json_schema_extra={"x-ref": "resource"},
                                    description="Other machines that can do this step with the same times")
    subcontract: Subcontract | None = Field(None, description="Done outside by a supplier instead of on a resource")

    @model_validator(mode="after")
    def _labor(self) -> Operation:
        if self.labor_hours_per_unit > 0 and not self.labor_resource:
            raise ValueError("labour hours per unit need a labour resource")
        if not self.resource and self.subcontract is None:
            raise ValueError("a step needs a machine, or a supplier who does it outside")
        if self.resource and self.subcontract is not None:
            raise ValueError("a step done outside does not use a machine here")
        if self.resource and self.resource in self.alternatives:
            raise ValueError("the machine is listed as its own alternative")
        return self


class ProductionSource(Model):
    """How to make a product at a plant: BOM + routing (≈ S/4 production version)."""

    id: Id
    location: str = Ref("location")
    product: str = Ref("product")
    output_qty: float = Unit("qty", gt=0, default=1.0, description="Base quantity the BOM refers to")
    components: list[BomItem] = Field(default_factory=list)
    operations: list[Operation] = Field(default_factory=list)
    co_products: list[CoProduct] = Field(default_factory=list,
                                         description="Other products the same run yields (co- and by-products)")
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
        # the same part may appear twice only as an engineering change: lines whose validity does not overlap
        by_part: dict[str, list[BomItem]] = {}
        for c in self.components:
            by_part.setdefault(c.product, []).append(c)
        for part, lines in by_part.items():
            lines = sorted(lines, key=lambda c: c.valid_from or date.min)
            for a, b in zip(lines, lines[1:], strict=False):
                if a.valid_to is None or b.valid_from is None or b.valid_from <= a.valid_to:
                    raise ValueError(f"{part} appears twice in the BOM for the same days — merge the lines, "
                                     "or give them valid-from and valid-to dates that follow each other")
        comps = set(by_part)
        if self.product in comps:
            raise ValueError("a product cannot be its own component")
        cos = [c.product for c in self.co_products]
        if len(cos) != len(set(cos)):
            raise ValueError("a co-product appears twice")
        if self.product in cos:
            raise ValueError("the main product cannot also be its own co-product")
        if comps & set(cos):
            raise ValueError("a product cannot be both a part and a co-product of the same run")
        if sum(c.cost_share for c in self.co_products) > 1 + 1e-9:
            raise ValueError("the co-products' cost shares add up to more than 100%")
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
            raise ValueError("from and to are the same place")
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
