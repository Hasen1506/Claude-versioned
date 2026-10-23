"""The warehouse inside a place (Enterprise 6.1, S/4 guide §12.2–12.3, a small EWM): storage types and bins, put-away
rules, warehouse tasks and waves.

Stock at a place stays the goods-movement journal's (:mod:`scp.model.actuals`); bins are a layer on it. A movement
names the bin its quantity comes from or goes to (``GoodsMovement.bin``); stock that names none is in no bin yet: in
the goods-in area after a receipt, or staged for goods issue after a pick. A warehouse task moves stock from one bin to
another and, confirmed, posts the pair of movements that does it (stock type ``status``, summing to zero at the place,
so planning never sees it). Places without bins work as before.
"""
from __future__ import annotations

import datetime as dt
from enum import Enum

from pydantic import Field, model_validator

from .actuals import StockType
from .common import Id, Model, Ref, Unit

BIN_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._/-]*$"


class Putaway(str, Enum):
    """Where a storage type puts goods away (≈ EWM put-away strategies)."""

    FIXED = "fixed"                  # the bins kept for the product (``Bin.product``)
    ADD = "add_to_stock"             # a bin holding the product already, with room; then the next empty bin
    EMPTY = "next_empty"             # the next empty bin along the walk


class StorageType(Model):
    """An area of a warehouse with one way of putting away (≈ EWM storage type): a high rack, a picking shelf, a cold
    room."""

    location: str = Ref("location", description="The plant or warehouse it is in")
    id: str = Field(min_length=1, max_length=20, pattern=BIN_PATTERN, description="Short code, unique per place")
    name: str = Field("", max_length=80)
    putaway: Putaway = Field(Putaway.EMPTY, description="Where goods are put away here")
    mixed: bool = Field(False, description="A bin here may hold several products at once")
    picking: bool = Field(True, description="Goods are picked from here (no: a reserve area, refilled from)")
    bins_per_product: int | None = Field(None, ge=1, le=9999, description="Most bins one product takes here (empty: "
                                         "no limit), so that one product does not fill a picking area")
    sequence: int = Field(10, ge=0, le=9999, description="Order in which put-away looks at the storage types when no "
                                                         "rule names them: lowest first")


class Bin(Model):
    """A storage bin (≈ EWM storage bin): the smallest place stock is kept in, its id the label read by the scanner."""

    location: str = Ref("location")
    id: str = Field(min_length=1, max_length=40, pattern=BIN_PATTERN,
                    description="The bin's label, as printed on its barcode (e.g. A-01-02)")
    storage_type: str = Field(min_length=1, max_length=20, description="The storage type it belongs to")
    walk: int = Field(0, ge=0, le=999999, description="Its place on the picking walk: picks are listed lowest first")
    max_qty: float | None = Unit("qty", default=None, description="Most it holds, in the products' own units "
                                                                   "(empty: no limit)")
    max_kg: float | None = Unit("kg", default=None, description="Most weight it holds (empty: no limit)")
    product: str | None = Ref("product", default=None, description="Kept for one product (fixed-bin put-away)")
    min_qty: float | None = Unit("qty", default=None,
                                 description="Refill point of a fixed picking bin: at or below it, the bin is refilled "
                                             "up to its most from the reserve (empty: refilled by hand)")
    blocked: bool = Field(False, description="Nothing is put away into it or picked from it")

    @model_validator(mode="after")
    def _refill(self) -> Bin:
        if self.min_qty is not None:
            if not self.product or not self.max_qty:
                raise ValueError("a bin refilled at a point is kept for one product and holds a most")
            if self.min_qty >= self.max_qty:
                raise ValueError("a bin's refill point is below the most it holds")
        return self


class PutawayRule(Model):
    """Which storage types a product is put away to, in order (≈ EWM storage type search sequence). The rule with no
    product holds for every product without a rule of its own."""

    location: str = Ref("location")
    product: str = Field("", max_length=64, description="The product (empty: every other product)")
    storage_types: list[str] = Field(min_length=1, max_length=20, description="Searched in this order")


class TaskKind(str, Enum):
    PUTAWAY = "putaway"
    PICK = "pick"
    MOVE = "move"


class WarehouseTask(Model):
    """One move of stock inside a place (≈ EWM warehouse task): put away from goods in to a bin, picked from a bin
    for a delivery, or moved between bins. Confirmed, it posts its movements."""

    id: Id
    location: str = Ref("location")
    kind: TaskKind
    product: str = Ref("product")
    batch: str | None = Field(None, max_length=40)
    stock_type: StockType = StockType.UNRESTRICTED
    qty: float = Unit("qty", gt=0)
    from_bin: str | None = Field(None, max_length=40, description="Empty: goods in (a put-away)")
    to_bin: str | None = Field(None, max_length=40, description="Empty: staged for goods issue (a pick)")
    wave: str | None = Field(None, max_length=20)
    delivery: str | None = Field(None, max_length=20, description="The delivery a pick is for")
    order: str | None = Field(None, max_length=64, description="The delivery's order line")
    created_on: dt.date
    status: str = Field("open", pattern=r"^(open|done|cancelled)$")
    done_qty: float | None = Unit("qty", default=None, description="What was moved: less than asked is short")
    done_on: dt.date | None = None
    done_by: str = Field("", max_length=120)
    movements: list[str] = Field(default_factory=list, max_length=4)
    note: str = Field("", max_length=200)


class Wave(Model):
    """Deliveries picked together (≈ EWM wave): one pick list over all their lines, in walk order."""

    id: str = Field(min_length=1, max_length=20)
    location: str = Ref("location")
    created_on: dt.date
    deliveries: list[str] = Field(min_length=1, max_length=500)
    note: str = Field("", max_length=200)
