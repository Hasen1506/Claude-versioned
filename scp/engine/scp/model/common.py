"""Shared field types and conventions for the whole data model.

Conventions (see docs/BLUEPRINT.md §3):
  * quantities are in the product's base UoM
  * money is in the company currency unless a ``currency`` field says otherwise
  * rates, shares, yields and service levels are FRACTIONS in [0, 1] — never percent
  * ``*_days`` are calendar days, ``*_workdays`` are working days, ``*_hours`` clock hours

Every field carries JSON-schema metadata (``x-unit``, ``x-ref``) so the web client can render
one consistent input component per unit kind and a picker for every reference.
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$"


class Model(BaseModel):
    """Base for every schema object: unknown keys are rejected, strings trimmed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, use_enum_values=False)


class Out(BaseModel):
    """Base for engine OUTPUT schemas: fields with defaults are still always present in responses,
    so the generated API types are exact (no optional-but-always-there fields)."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


def _extra(unit: str | None = None, ref: str | None = None, **more: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if unit:
        out["x-unit"] = unit
    if ref:
        out["x-ref"] = ref
    out.update(more)
    return out


def Unit(unit: str, *, ge: float | None = 0, le: float | None = None, gt: float | None = None,
         lt: float | None = None, default: Any = ..., description: str = "", **kw: Any) -> Any:
    """A numeric field with an explicit unit kind for the UI (``fraction``, ``days``, ``hours``,
    ``qty``, ``money``, ``kg``, ``m3``, ``money_per_unit``…)."""
    if gt is not None or lt is not None:
        ge = None if gt is not None else ge
    return Field(default, ge=ge, le=le, gt=gt, lt=lt, description=description,
                 json_schema_extra=_extra(unit), **kw)


def Ref(kind: str, *, default: Any = ..., description: str = "") -> Any:
    """A string reference to another object by id (``location``, ``product``, ``resource``…)."""
    return Field(default, description=description, json_schema_extra=_extra(ref=kind))


Id = Annotated[str, Field(min_length=1, max_length=64, pattern=ID_PATTERN)]


class LocationType(str, Enum):
    PLANT = "plant"
    DC = "dc"
    WAREHOUSE = "warehouse"
    STORE = "store"
    SUPPLIER = "supplier"
    CUSTOMER = "customer"


STOCKING_LOCATION_TYPES = {LocationType.PLANT, LocationType.DC, LocationType.WAREHOUSE, LocationType.STORE}
PRODUCTION_LOCATION_TYPES = {LocationType.PLANT}


class ProductType(str, Enum):
    FG = "FG"      # finished good (sellable)
    SFG = "SFG"    # semi-finished / sub-assembly
    RM = "RM"      # raw material / purchased component
    PKG = "PKG"    # packaging


class Strategy(str, Enum):
    """Planning strategy (S/4 guide §5.2)."""

    MTS = "MTS"                  # SAP 10: forecast drives supply, orders do not consume it
    MTS_CONSUME = "MTS_CONSUME"  # SAP 40: orders consume forecast within the consumption window
    MTO = "MTO"                  # SAP 20: each sales order drives its own supply, forecast ignored
    ATO = "ATO"                  # SAP 50: forecast pre-plans components; final assembly on order


class MrpType(str, Enum):
    DETERMINISTIC = "deterministic"   # SAP PD
    REORDER_POINT = "reorder_point"   # SAP VB
    NONE = "none"                     # SAP ND — projected, never replenished


class LotSizePolicy(str, Enum):
    L4L = "L4L"          # lot-for-lot (SAP EX)
    FIXED = "FIXED"      # fixed lot, repeated until covered (SAP FX)
    EOQ = "EOQ"          # economic order quantity
    POQ = "POQ"          # periodic: cover the next N buckets (SAP WB/MB/PK)
    MIN_MAX = "MIN_MAX"  # replenish up to max stock (SAP HB)


class SafetyStockMethod(str, Enum):
    NONE = "none"
    FIXED = "fixed"
    DAYS_OF_SUPPLY = "days_of_supply"   # dynamic coverage profile
    SERVICE_LEVEL = "service_level"     # cycle service level (alpha)
    FILL_RATE = "fill_rate"             # beta service level


class ResourceKind(str, Enum):
    MACHINE = "machine"
    LINE = "line"
    LABOR = "labor"
    TOOL = "tool"


class TransportMode(str, Enum):
    TRUCK_FTL = "truck_ftl"
    TRUCK_LTL = "truck_ltl"
    RAIL = "rail"
    SEA = "sea"
    AIR = "air"
    COURIER = "courier"
    PIPELINE = "pipeline"


class BucketSize(str, Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class DemandKind(str, Enum):
    FORECAST = "forecast"
    SALES_ORDER = "sales_order"


class ReceiptKind(str, Enum):
    PURCHASE = "purchase"
    PRODUCTION = "production"
    TRANSFER = "transfer"
